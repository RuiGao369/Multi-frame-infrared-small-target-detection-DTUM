import torch
import torch.nn as nn
import torch.nn.functional as F


class MyWeightBCETopKLoss(nn.Module):
    def __init__(self,gamma=0, alpha=None, size_average=False, MaxClutterNum=39, ProtectedArea=2):
        super(MyWeightBCETopKLoss, self).__init__()

        self.bce_loss = nn.BCEWithLogitsLoss(reduce=False)

        self.HardRatio = 1/4
        self.HardNum = round(MaxClutterNum*self.HardRatio)
        self.EasyNum = MaxClutterNum - self.HardNum

        self.MaxClutterNum = MaxClutterNum
        self.ProtectedArea = ProtectedArea
        self.gamma=gamma
        self.alpha=alpha
        self.size_average = size_average
        if isinstance(alpha, (float, int)): self.alpha=torch.Tensor([alpha(0), alpha(1)])
        # if isinstance(alpha, (float, int)): self.alpha = torch.Tensor(alpha)
        if isinstance(alpha, list): self.alpha=torch.Tensor(alpha)


    def forward(self, input, target):   ## Input: [2,1,512,512]    Target: [2,1,512,512]

        if input.dim() > 4:
            input = torch.squeeze(input, 2)

        ## target surrounding = 2
        template = torch.ones(1, 1, 2*self.ProtectedArea+1, 2*self.ProtectedArea+1).to(input.device)    ## [1,1,5,5]
        target_prot = F.conv2d(target.float(), template, stride=1, padding=self.ProtectedArea)          ## [2,1,512,512]
        target_prot = (target_prot > 0).float()

        with torch.no_grad():
            loss_wise = self.bce_loss(input, target.float())        ## learning based on result of loss computing
            loss_p = loss_wise * (1 - target_prot)
            idx = torch.randperm(130) + 20

            batch_l = loss_p.shape[0]
            Wgt = torch.zeros(batch_l, 1, 512, 512)
            for ls in range(batch_l):
                loss_ls = loss_p[ls, :, :, :].reshape(-1)
                loss_topk, indices = torch.topk(loss_ls, 200)
                indices_rand = indices[idx[0:self.HardNum]]         ## random select HardNum samples in top [20-150]
                idx_easy = torch.randperm(len(loss_ls))[0:self.EasyNum].to(input.device)  ## random select EasyNum samples in all image
                indices_rand = torch.cat((indices_rand, idx_easy), 0)
                indices_rand_row = indices_rand // 512
                indices_rand_col = indices_rand % 512
                Wgt[ls, 0, indices_rand_row, indices_rand_col] = 1


            WgtData_New = Wgt.to(input.device)*(1-target_prot) + target.float()
            WgtData_New[WgtData_New > 1] = 1

        logpt = F.logsigmoid(input)
        logpt_bk = F.logsigmoid(-input)
        pt = logpt.data.exp()
        pt_bk = 1 - logpt_bk.data.exp()
        loss = -self.alpha[1]*(1-pt)**self.gamma*target*logpt - self.alpha[0]*pt_bk**self.gamma*(1-target)*logpt_bk

        loss = loss * WgtData_New

        return loss.sum()

        # if input.dim()>2:
        #     input=input.view(input.size(0), input.size(1),-1)   # N,C,D,H,W=>N,C,D*H*W
        #     input=input.transpose(1,2)                          # N,C,D*H*W=>N, D*H*W, C
        #     input=input.contiguous().view(-1,input.size(2))     # N,D*H*W,C=>N*D*H*W, C
        #
        #     WgtData_New = WgtData_New.view(WgtData_New.size(0), WgtData_New.size(1), -1)    # N,C,D,H,W=>N,C,D*H*W
        #     WgtData_New = WgtData_New.transpose(1, 2)                               # N,C,D*H*W=>N, D*H*W,C
        #     WgtData_New = WgtData_New.contiguous().view(-1, WgtData_New.size(2))        # N,D*H*W,C=>N*D*H*W,C
        #
        # target = target.view(-1,1)     ## [2*1*512*512,1]     #N,D,H,W=>1,N*D*H*W
        # logpt = F.log_softmax(input, dim=1)   ## [2*1*512*512,2]
        # logpt = logpt.gather(1,target) ##  zhiding rank 2 target
        # logpt = logpt*WgtData_New        #weight  ## predit of concern 39+1
        # logpt = logpt.view(-1)           #possibility of target
        # pt=logpt.data.exp()
        #
        #
        # if self.alpha is not None:
        #     if self.alpha.type()!=input.data.type():
        #         self.alpha=self.alpha.type_as(input.data).to(input.device)
        #     at=self.alpha.gather(0,target.data.view(-1))
        #     logpt=logpt*at   ##at= alpha
        #
        # loss=-1*(1-pt)**self.gamma*logpt


