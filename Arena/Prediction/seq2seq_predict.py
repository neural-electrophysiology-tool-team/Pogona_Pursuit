import torch
from torch import nn
from Prediction.predictor import TrajectoryPredictor
import math


class Seq2SeqPredictor(TrajectoryPredictor):
    """
    A TrajectoryPredictor subclass that uses a pytorch model to generate forecasts.
    """

    def __init__(self, model, weights_path, input_len, forecast_horizon):
        """
        The model is sent to the available device, and weights are loaded from the file.
        :param model: An initialized PyTorch seq2seq model (torch.nn.Module).
        :param weights_path: Path to a pickled state dictionary containing trained weights for the model.
        :param input_len: Number of timesteps to look back in order to generate a forecast.
        :param forecast_horizon: The forecast size in timesteps into the future.
        """
        super().__init__(input_len, forecast_horizon)

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = model.to(self.device).float()
        self.model.load_state_dict(torch.load(weights_path))
        self.model.eval()

    def init_trajectory(self, detection):
        pass

    def _update_and_predict(self, past_input):
        """
        Receive an updated bbox history and generate and return a forecast trajectory by feed foraward the input
        through the model
        """

        with torch.no_grad():
            inp = torch.from_numpy(past_input).to(self.device)
            inp = inp.unsqueeze(0).float()  # PyTorch RNN's require a 3 dimensional Tensor as input
            forecast = self.model(inp)
            return forecast.squeeze().cpu().numpy()


class LSTMdense(nn.Module):
    def __init__(
            self,
            output_seq_size,
            embedding_size=None,
            hidden_size=128,
            LSTM_layers=2,
            dropout=0.0,
    ):
        """
        Implementation of RED predictor - LSTM for encoding and Linear layer for decoding.
        "RED: A simple but effective Baseline Predictor for the TrajNet Benchmark"
        From pedestrian trajectory prediction literature

        :param output_seq_size: forecast length
        :param embedding_size: output dimension of linear embedding layer of input (default: None)
        :param hidden_size: dimension of hidden vector in each LSTM layer
        :param LSTM_layers: number of LSTM layers
        :param dropout: dropout normalization probability (default: 0)
        """
        super(LSTMdense, self).__init__()

        self.hidden_size = hidden_size
        self.LSTM_layers = LSTM_layers
        self.output_seq_size = output_seq_size
        self.output_dim = 4 * output_seq_size

        if embedding_size is not None:
            self.embedding_encoder = nn.Linear(in_features=4, out_features=embedding_size)
        else:
            embedding_size = 4
            self.embedding_encoder = None

        self.dropout = nn.Dropout(dropout)

        self.LSTM = nn.LSTM(input_size=embedding_size,
                            hidden_size=hidden_size,
                            num_layers=LSTM_layers,
                            dropout=dropout, ) # TODO: add batch first and remove transpose from forward?

        self.out_dense = nn.Linear(in_features=hidden_size, out_features=self.output_dim)

    def forward(self, input_seq):
        # take the last coordinates from the input sequence and tile them to the output length shape, switch dims 0,1
        offset = input_seq[:, -1].repeat(self.output_seq_size, 1, 1).transpose(0, 1)

        # compute diffs
        diffs = input_seq[:, 1:] - input_seq[:, :-1]

        if self.embedding_encoder is not None:
            diffs = self.embedding_encoder(diffs)

        inp = self.dropout(diffs)

        # ignores output (0) and cell (1,1)
        _, (h_out, _) = self.LSTM(inp.transpose(0, 1))

        output = self.out_dense(h_out[-1])  # take hidden state of last layer
        output_mat = output.view(-1, self.output_seq_size, 4)

        # add the offset to the deltas output
        return offset + output_mat


# TODO: needed?
class PositionalEncoding(nn.Module):
    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer("pe", pe)

    def forward(self, x):
        x = x + self.pe[: x.size(0), :]
        return self.dropout(x)


class GRUEncDec(nn.Module):
    def __init__(
            self,
            output_seq_size=20,
            hidden_size=64,
            GRU_layers=1,
            dropout=0.0,
            tie_enc_dec=False,
            use_gru_cell=False
    ):
        """
        Encoder-decoder architechture with GRU cells as encoder and decoder
        :param output_seq_size: forecast length (defualt: 20)
        :param hidden_size: dimension of hidden state in GRU cell (defualt: 64)
        :param GRU_layers: number of GRU layers (defualt: 1)
        :param dropout: probablity of dropout of input (default: 0)
        :param tie_enc_dec: Boolean, whether to use the same parameters in the encoder and decoder (default: False)
        :param use_gru_cell: Boolean, whether to use the nn.GRUCell class instead of nn.GRU (default: False)
        """
        super(GRUEncDec, self).__init__()

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.output_seq_size = output_seq_size
        self.hidden_size = hidden_size
        self.tie_enc_dec = tie_enc_dec
        self.use_gru_cell = use_gru_cell

        self.dropout_layer = torch.nn.Dropout(dropout)

        self.encoderGRU = nn.GRU(input_size=4,
                                 hidden_size=hidden_size,
                                 num_layers=GRU_layers,
                                 batch_first=True,
                                 )

        if not tie_enc_dec:
            if use_gru_cell:
                self.decoderGRU = nn.GRUCell(input_size=4,
                                             hidden_size=hidden_size,
                                             )
            else:
                self.decoderGRU = nn.GRU(input_size=4,
                                         hidden_size=hidden_size,
                                         num_layers=GRU_layers,
                                         batch_first=True,
                                         )
        else:
            self.decoderGRU = self.encoderGRU

        self.linear = nn.Linear(in_features=hidden_size, out_features=4)

    def forward(self, input_seq):
        offset = input_seq[:, -1].repeat(self.output_seq_size, 1, 1).transpose(0, 1)
        diffs = input_seq[:, 1:] - input_seq[:, :-1]

        diffs = self.dropout_layer(diffs)

        _, hn = self.encoderGRU(diffs)
        out_list = []

        # prev_x = input_seq[:, -1]
        prev_x = diffs[:, -1]
        # prev_x = torch.zeros(diffs[:, -1].size()).to(self.device) # doesn't seem to make a difference...

        if self.use_gru_cell:
            hn = hn[0]

        for i in range(self.output_seq_size):
            if self.use_gru_cell:
                hn = self.decoderGRU(prev_x, hn)
                lin = self.linear(hn)
            else:
                _, hn = self.decoderGRU(prev_x.unsqueeze(1), hn)
                lin = self.linear(hn[-1])

            x = lin + prev_x
            out_list.append(x.unsqueeze(1))
            prev_x = x

        out = torch.cat(out_list, dim=1)
        # add the deltas to the last location
        # cumsum marginally improves generalization
        return out.cumsum(dim=1) + offset


class ConvEncoder(nn.Module):
    def __init__(self, in_width, in_height, out_size, conv1_out_chan, conv2_out_chan):
        """
        Convolutional encoder to map cropped head image to a low dimensional vector. Trained jointly with
        the the rest of the network. Constant architechture with 2 conv layers.
        :param in_width: image width
        :param in_height: image height
        :param out_size: 1d dimension of the embedding vector
        :param conv1_out_chan: number of kernels in conv1
        :param conv2_out_chan: number of kernels in conv2
        """
        super().__init__()
        self.conv1 = torch.nn.Conv2d(in_channels=1, out_channels=conv1_out_chan, kernel_size=3)
        self.conv2 = torch.nn.Conv2d(in_channels=conv1_out_chan, out_channels=conv2_out_chan, kernel_size=3)
        self.pool = torch.nn.MaxPool2d(2)

        inp = torch.rand(1, 1, in_width, in_height)
        inp = self.conv1(inp)
        inp = self.pool(inp)
        inp = self.conv2(inp)
        inp = self.pool(inp)

        self.fc = torch.nn.Linear(inp.flatten().size(0), out_size)

        self.out_size = out_size
        self.in_width = in_width
        self.in_height = in_height

    def forward(self, x):
        x = self.conv1(x)
        x = torch.nn.functional.relu(x)
        x = self.pool(x)
        x = self.conv2(x)
        x = torch.nn.functional.relu(x)
        x = self.pool(x)
        return self.fc(x.reshape(x.size(0), -1))


class GRUEncDecWithHead(nn.Module):
    def __init__(
            self,
            output_seq_size=20,
            hidden_size=64,
            GRU_layers=1,
            dropout=0.0,
            head_embedder=ConvEncoder(32, 32, 5, 4, 10),
    ):
        """
        Encoder-decoder architechture with GRU cells as encoder and decoder
        :param output_seq_size: forecast length (defualt: 20)
        :param hidden_size: dimension of hidden state in GRU cell (defualt: 64)
        :param GRU_layers: number of GRU layers (defualt: 1)
        :param dropout: probability of dropout of input (default: 0)
        :param tie_enc_dec: Boolean, whether to use the same parameters in the encoder and decoder (default: False)
        :param use_gru_cell: Boolean, whether to use the nn.GRUCell class instead of nn.GRU (default: False)
        :param head_embedder: initialized torch.nn module to map cropped head image to a low dimensional vector
        """
        super().__init__()

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.output_seq_size = output_seq_size
        self.hidden_size = hidden_size

        self.dropout_layer = torch.nn.Dropout(dropout)

        self.encoderGRU = nn.GRU(input_size=4 + head_embedder.out_size,
                                 hidden_size=hidden_size,
                                 num_layers=GRU_layers,
                                 batch_first=True,
                                 )

        self.decoderGRU = nn.GRUCell(input_size=4,
                                     hidden_size=hidden_size)

        self.linear = nn.Linear(in_features=hidden_size, out_features=4)

        self.head_embedder = head_embedder

    def forward(self, bbox_seq, head_seq):
        offset = bbox_seq[:, -1].repeat(self.output_seq_size, 1, 1).transpose(0, 1)
        diffs = bbox_seq[:, 1:] - bbox_seq[:, :-1]

        diffs = self.dropout_layer(diffs)

        # drop last head image, unnecessary for diffs
        head_seq = head_seq[:, :-1]

        # reshape tensor for batch inference of images
        head_input = head_seq.unsqueeze(2).reshape(-1, 1, head_seq.size(-2), head_seq.size(-1))
        head_embedding = self.head_embedder(head_input)

        # reshape tensor back to (batch, sequence) dimensions.
        head_embedding = head_embedding.reshape(diffs.size(0), diffs.size(1), -1)

        _, hn = self.encoderGRU(torch.cat([diffs, head_embedding], dim=2))
        out_list = []

        # prev_x = input_seq[:, -1]
        prev_x = diffs[:, -1]
        # prev_x = torch.zeros(diffs[:, -1].size()).to(self.device) # doesn't seem to make a difference...

        hn = hn[0]

        for i in range(self.output_seq_size):
            hn = self.decoderGRU(prev_x, hn)
            lin = self.linear(hn)

            x = lin + prev_x
            out_list.append(x.unsqueeze(1))
            prev_x = x

        out = torch.cat(out_list, dim=1)
        # add the deltas to the last location
        # cumsum marginally improves generalization
        return out.cumsum(dim=1) + offset
 

class GRUPositionEncDec(nn.Module):
    def __init__(
            self,
            output_size=2,
            output_seq_size=20,
            hidden_size=64,
            embedding_size=8,
            GRU_layers=1,
            dropout=0.0,
            tie_enc_dec=False,
    ):
        super(GRUPositionEncDec, self).__init__()

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.output_size = output_size
        self.output_seq_size = output_seq_size
        self.hidden_size = hidden_size
        self.tie_enc_dec = tie_enc_dec

        self.vel_embed = torch.nn.Linear(in_features=2, out_features=embedding_size)
        # self.pos_embed = torch.nn.Linear(in_features=2, out_features=embedding_size)
        self.pos_embed = PositionalEncoding(embedding_size)

        # self.dropout_layer = torch.nn.Dropout(dropout)

        self.encoderGRU = nn.GRU(
            input_size=embedding_size,
            hidden_size=hidden_size,
            num_layers=GRU_layers,
            batch_first=True,
        )

        if not tie_enc_dec:
            self.decoderGRU = nn.GRU(
                input_size=embedding_size,
                hidden_size=hidden_size,
                num_layers=GRU_layers,
                batch_first=True,
            )
        else:
            self.decoderGRU = self.encoderGRU

        self.linear = nn.Linear(in_features=hidden_size, out_features=output_size)

    def forward(self, input_seq):
        offset = input_seq[:, -1, :2].repeat(self.output_seq_size, 1, 1).transpose(0, 1)
        diffs = input_seq[:, 1:, :2] - input_seq[:, :-1, :2]

        vel_embedding = self.vel_embed(diffs)
        # pos_embedding = self.pos_embed(input_seq[:, :-1])
        embedding = self.pos_embed(vel_embedding)

        _, hn = self.encoderGRU(embedding)
        out_list = []

        prev_x = diffs[:, -1]

        for i in range(self.output_seq_size):
            prev_x_embedding = self.vel_embed(prev_x)
            _, hn = self.decoderGRU(prev_x_embedding.unsqueeze(1), hn)
            lin = self.linear(hn[-1])
            x = lin + prev_x
            out_list.append(x.unsqueeze(1))
            prev_x = x

        out = torch.cat(out_list, dim=1)
        # return out
        return out + offset


class VelLinear(nn.Module):
    def __init__(
            self,
            input_size=2,
            output_size=2,
            input_seq_size=20,
            output_seq_size=20,
            hidden_size=64,
            dropout=0.0,
    ):
        super(VelLinear, self).__init__()

        self.output_size = output_size
        self.output_seq_size = output_seq_size
        self.input_seq_size = output_seq_size

        self.dropout_layer = torch.nn.Dropout(dropout)
        self.encoder = torch.nn.Linear(
            in_features=input_size * (input_seq_size - 1), out_features=hidden_size
        )
        self.decoder = torch.nn.Linear(
            in_features=hidden_size, out_features=output_size * output_seq_size
        )

    def forward(self, input_seq):
        offset = input_seq[:, -1, :2].repeat(self.output_seq_size, 1, 1).transpose(0, 1)
        diffs = input_seq[:, 1:] - input_seq[:, :-1]

        x = self.dropout_layer(diffs)
        x = self.encoder(x.view(x.shape[0], -1))
        x = torch.nn.functional.relu(x)
        x = self.decoder(x)

        out = x.view(x.shape[0], self.input_seq_size, self.output_size)

        return out + offset